"""Deterministic checks for AEGIS graph, routing, and simulation behavior."""

from __future__ import annotations

import unittest
from copy import deepcopy

from aegis.building import build_generated_building, build_sample_building, validate_building
from aegis.models import Building, Edge, Node, Person, Sensor, SimulationState
from aegis.routing import find_route
from aegis.simulation import (
    assign_group_routes,
    create_scenario,
    inject_sensor_alarm,
    log_event,
    set_running,
    step_simulation,
)
from aegis.visualization import build_route_instructions, render_floor_map, route_floor_sequence


def make_two_path_building() -> Building:
    nodes = {
        "S": Node("S", 0, 0, 0, "room", "Start Room"),
        "D": Node("D", 0, 1, 0, "junction", "Direct Junction"),
        "A": Node("A", 0, 1, 1, "junction", "Alternate Junction"),
        "X": Node("X", 0, 2, 0, "exit", "Exit X", exit_capacity=2),
    }
    edges = {
        "E-SD": Edge("E-SD", "S", "D", 1, 1.5, 3),
        "E-DX": Edge("E-DX", "D", "X", 1, 1.5, 3),
        "E-SA": Edge("E-SA", "S", "A", 2, 1.5, 3),
        "E-AX": Edge("E-AX", "A", "X", 2, 1.5, 3),
    }
    return Building(nodes, edges)


def make_midroute_reroute_building() -> Building:
    building = make_two_path_building()
    edges = dict(building.edges)
    edges["E-DA"] = Edge("E-DA", "D", "A", 1.0, 1.5, 3)
    return Building(dict(building.nodes), edges)


def make_split_building() -> Building:
    nodes = {
        "S": Node("S", 0, 0, 0, "room", "Start"),
        "JA": Node("JA", 0, 1, 1, "junction", "A junction"),
        "JB": Node("JB", 0, 1, -1, "junction", "B junction"),
        "XA": Node("XA", 0, 2, 1, "exit", "Exit A", exit_capacity=2),
        "XB": Node("XB", 0, 2, -1, "exit", "Exit B", exit_capacity=2),
    }
    edges = {
        "A-1": Edge("A-1", "S", "JA", 1, 1.5, 1),
        "A-2": Edge("A-2", "JA", "XA", 1, 1.5, 1),
        "B-1": Edge("B-1", "S", "JB", 1, 1.5, 1),
        "B-2": Edge("B-2", "JB", "XB", 1, 1.5, 1),
    }
    return Building(nodes, edges)


def make_single_corridor_building(exit_capacity: int = 1) -> Building:
    nodes = {
        "S": Node("S", 0, 0, 0, "room", "Start Room"),
        "J": Node("J", 0, 1, 0, "junction", "Narrow Junction"),
        "X": Node("X", 0, 2, 0, "exit", "Only Exit", exit_capacity=exit_capacity),
    }
    edges = {
        "E-SJ": Edge("E-SJ", "S", "J", 1, 0.8, 1, is_narrow=True),
        "E-JX": Edge("E-JX", "J", "X", 1, 1.0, 1),
    }
    return Building(nodes, edges)


class BuildingAndRoutingTests(unittest.TestCase):
    def test_sample_graph_is_valid_and_has_three_floors_two_stairs_and_exits(self):
        building = build_sample_building()
        self.assertEqual(validate_building(building), [])
        self.assertEqual({node.floor for node in building.nodes.values()}, {0, 1, 2})
        self.assertEqual(sum(node.kind == "exit" for node in building.nodes.values()), 2)
        self.assertEqual(sum(edge.is_stair for edge in building.edges.values()), 4)
        self.assertTrue(any(edge.is_narrow for edge in building.edges.values()))

    def test_generated_buildings_are_seeded_varied_and_reachable(self):
        first = build_generated_building(801, "School", floor_count=4, rooms_per_wing=3)
        replay = build_generated_building(801, "School", floor_count=4, rooms_per_wing=3)
        different = build_generated_building(802, "Hospital", floor_count=5, rooms_per_wing=4)

        self.assertEqual(validate_building(first), [])
        self.assertEqual(first.nodes, replay.nodes)
        self.assertEqual(first.edges, replay.edges)
        self.assertNotEqual(first.nodes, different.nodes)
        self.assertEqual({node.floor for node in first.nodes.values()}, {0, 1, 2, 3})
        self.assertEqual({node.floor for node in different.nodes.values()}, {0, 1, 2, 3, 4})
        self.assertTrue(any(node.label.startswith("Classroom") for node in first.nodes.values()))

    def test_scenario_can_use_a_generated_building(self):
        building = build_generated_building(803, "Mall", floor_count=4, rooms_per_wing=3)
        state = create_scenario(8, 803, "Fire / smoke", building=building)

        self.assertIs(state.building, building)
        self.assertEqual(validate_building(state.building), [])
        self.assertEqual(len([sensor for sensor in state.sensors if sensor.target_kind == "edge"]), len(building.edges))
        self.assertEqual({state.building.nodes[person.current_node].floor for person in state.people}, {0, 1, 2, 3})

    def test_dijkstra_returns_expected_shortest_path(self):
        building = make_two_path_building()
        route = find_route(building, "S")
        self.assertIsNotNone(route)
        self.assertEqual(route.nodes, ("S", "D", "X"))
        self.assertEqual(route.edges, ("E-SD", "E-DX"))

    def test_blocked_node_uses_safe_alternative_and_blocked_edges_can_fail(self):
        building = make_two_path_building()
        route = find_route(building, "S", blocked_nodes={"D"})
        self.assertIsNotNone(route)
        self.assertEqual(route.nodes, ("S", "A", "X"))
        self.assertIsNone(find_route(building, "S", blocked_edges={"E-SD", "E-SA"}))

    def test_caution_area_remains_usable_when_it_is_the_only_route(self):
        building = make_two_path_building()
        route = find_route(building, "S", blocked_edges={"E-SA"}, caution_nodes={"D"})
        self.assertIsNotNone(route)
        self.assertEqual(route.nodes, ("S", "D", "X"))


class ScenarioTests(unittest.TestCase):
    def test_same_seed_reproduces_hazard_sensors_people_and_routes(self):
        first = create_scenario(12, 20261023)
        second = create_scenario(12, 20261023)
        self.assertEqual(first.hazards, second.hazards)
        self.assertEqual(first.sensors, second.sensors)
        self.assertEqual(first.people, second.people)
        self.assertEqual(first.blocked_nodes, second.blocked_nodes)
        self.assertEqual(first.blocked_edges, second.blocked_edges)

    def test_each_hazard_can_be_selected_with_a_seeded_random_spawn(self):
        for incident_type in ("Fire / smoke", "Gas leak", "Blocked passage", "Earthquake"):
            with self.subTest(incident_type=incident_type):
                first = create_scenario(6, 212, incident_type)
                second = create_scenario(6, 212, incident_type)
                hazard = first.hazards[0]
                self.assertEqual(hazard, second.hazards[0])
                self.assertEqual(hazard.incident_type, incident_type)
                if incident_type in {"Fire / smoke", "Gas leak"}:
                    self.assertEqual(hazard.target_kind, "node")
                    self.assertEqual(first.building.nodes[hazard.target_id].kind, "room")
                elif incident_type == "Blocked passage":
                    self.assertEqual(hazard.target_kind, "edge")
                    self.assertFalse(first.building.edges[hazard.target_id].is_stair)
                else:
                    self.assertTrue(
                        hazard.target_kind == "edge"
                        or first.building.nodes[hazard.target_id].kind == "junction"
                    )
                sensor = next(
                    item for item in first.sensors
                    if item.target_id == hazard.target_id and item.target_kind == hazard.target_kind
                )
                if incident_type == "Earthquake":
                    self.assertEqual(sensor.metric, "ground_motion")
        self.assertEqual(create_scenario(2, 55, "Random incident").hazards[0].incident_type,
                         create_scenario(2, 55).hazards[0].incident_type)
        with self.assertRaises(ValueError):
            create_scenario(2, 55, "Tornado")

    def test_people_count_and_safe_distributed_placements(self):
        one = create_scenario(1, 7)
        twenty = create_scenario(20, 7)
        self.assertEqual(len(one.people), 1)
        self.assertEqual(len(twenty.people), 20)
        self.assertTrue(all(person.current_node not in twenty.blocked_nodes for person in twenty.people))
        starting_rooms = {person.start_node for person in twenty.people}
        self.assertGreaterEqual(len(starting_rooms), 3)
        self.assertEqual({twenty.building.nodes[node].floor for node in starting_rooms}, {0, 1, 2})
        with self.assertRaises(ValueError):
            create_scenario(0, 7)
        with self.assertRaises(ValueError):
            create_scenario(21, 7)

    def test_small_groups_are_spread_across_different_floors(self):
        for count in (1, 2, 3):
            with self.subTest(count=count):
                state = create_scenario(count, 700 + count)
                occupied_floors = {
                    state.building.nodes[person.start_node].floor for person in state.people
                }
                self.assertEqual(len(occupied_floors), count)

    def test_route_map_and_turn_by_turn_view_do_not_mutate_simulation(self):
        state = create_scenario(20, 91)
        before_render = deepcopy(state)
        upper_floor_person = next(
            person for person in state.people
            if state.building.nodes[person.current_node].floor == 2 and person.route
        )

        figure = render_floor_map(state, 2, upper_floor_person.id)
        route_names = {trace.name for trace in figure.data}
        directions = build_route_instructions(state, upper_floor_person)

        self.assertIn(f"{upper_floor_person.id} safe route", route_names)
        self.assertEqual(route_floor_sequence(state, upper_floor_person), [2, 1, 0])
        self.assertTrue(any("down to Floor 1" in direction for direction in directions))
        self.assertTrue(any("down to Ground" in direction for direction in directions))
        self.assertEqual(state, before_render)

    def test_evacuated_person_keeps_their_traveled_route_for_inspection(self):
        state = SimulationState(building=make_single_corridor_building(), seed=15)
        person = Person("P01", "S", "S")
        state.people = [person]
        assign_group_routes(state)
        set_running(state, True)
        for _ in range(11):
            step_simulation(state)

        self.assertNotEqual(person.status, "Evacuated")
        self.assertEqual(person.current_node, "S")
        self.assertAlmostEqual(person.movement_progress, 11 / 12)

        for _ in range(13):
            step_simulation(state)

        self.assertEqual(person.status, "Evacuated")
        self.assertEqual(person.route, [])
        self.assertEqual(person.traversed_nodes, ["S", "J", "X"])
        self.assertEqual(person.traversed_edges, ["E-SJ", "E-JX"])
        self.assertEqual(route_floor_sequence(state, person), [0])
        figure = render_floor_map(state, 0, person.id)
        self.assertIn(f"{person.id} traveled path", {trace.name for trace in figure.data})

    def test_exit_labels_point_inward_on_the_floor_map(self):
        state = create_scenario(8, 44)
        figure = render_floor_map(state, 0, state.people[0].id)
        exits = next(trace for trace in figure.data if trace.name == "Safe exits")

        self.assertEqual(list(exits.text), ["West Exit", "East Exit"])
        self.assertEqual(list(exits.textposition), ["top right", "top left"])

    def test_selected_person_stays_visible_and_wrong_floor_is_explained(self):
        state = create_scenario(8, 44)
        person = state.people[0]
        person_floor = state.building.nodes[person.current_node].floor
        figure = render_floor_map(state, person_floor, "stale-selection")
        marker = next(trace for trace in figure.data if trace.name.startswith("Selected person"))

        self.assertEqual(list(marker.text), [person.id])
        self.assertEqual(marker.marker.size, 18)

        other_floor = (person_floor + 1) % 3
        other_figure = render_floor_map(state, other_floor, person.id)
        self.assertIn(
            f"{person.id} is currently on {('Ground', 'Floor 1', 'Floor 2')[person_floor]}",
            {annotation.text for annotation in other_figure.layout.annotations},
        )

    def test_navigation_route_turns_grey_behind_the_walking_person(self):
        state = SimulationState(building=make_single_corridor_building(), seed=16)
        person = Person("P01", "S", "S")
        state.people = [person]
        assign_group_routes(state)
        set_running(state, True)
        for _ in range(6):
            step_simulation(state)

        figure = render_floor_map(state, 0, person.id)
        completed = next(trace for trace in figure.data if trace.name == f"{person.id} traveled path")
        remaining = next(trace for trace in figure.data if trace.name == f"{person.id} safe route")
        marker = next(trace for trace in figure.data if trace.name.startswith("Selected person"))

        self.assertEqual(completed.line.color, "#64748b")
        self.assertEqual(remaining.line.color, "#2563eb")
        self.assertAlmostEqual(completed.x[1], marker.x[0])
        self.assertAlmostEqual(remaining.x[0], marker.x[0])
        self.assertLess(figure.layout.xaxis.range[1] - figure.layout.xaxis.range[0], 23)
        self.assertEqual(figure.layout.transition.duration, 800)

    def test_priority_is_higher_at_a_shorter_graph_distance_to_hazard(self):
        state = create_scenario(20, 34)
        hazard = state.hazards[0]
        if hazard.target_kind == "edge":
            target_nodes = {state.building.edges[hazard.target_id].a, state.building.edges[hazard.target_id].b}
        else:
            target_nodes = {hazard.target_id}

        def distance_to_hazard(start: str) -> float:
            distances = {start: 0.0}
            pending = [(0.0, start)]
            import heapq
            while pending:
                distance, node_id = heapq.heappop(pending)
                if distance != distances.get(node_id):
                    continue
                if node_id in target_nodes:
                    return distance
                for neighbor, edge in state.building.neighbors(node_id):
                    candidate = distance + edge.travel_time
                    if candidate < distances.get(neighbor.id, float("inf")):
                        distances[neighbor.id] = candidate
                        heapq.heappush(pending, (candidate, neighbor.id))
            return float("inf")

        people = sorted(state.people, key=lambda person: distance_to_hazard(person.current_node))
        nearest = distance_to_hazard(people[0].current_node)
        farthest = distance_to_hazard(people[-1].current_node)
        self.assertLessEqual(nearest, farthest)
        self.assertGreaterEqual(people[0].priority_score, people[-1].priority_score)
        self.assertAlmostEqual(people[0].priority_score, 1.0 / (0.5 + nearest))

    def test_shared_group_routing_splits_people_between_exits(self):
        state = SimulationState(building=make_split_building(), seed=1)
        state.people = [Person(f"P{i:02d}", "S", "S") for i in range(1, 6)]
        assign_group_routes(state)
        assigned_exits = {person.assigned_exit for person in state.people}
        self.assertEqual(assigned_exits, {"XA", "XB"})

    def test_step_replans_from_current_location_when_route_edge_closes(self):
        state = SimulationState(building=make_two_path_building(), seed=8)
        person = Person("P01", "S", "S")
        state.people = [person]
        assign_group_routes(state)
        self.assertEqual(person.route, ["S", "D", "X"])

        state.blocked_edges.add("E-SD")
        step_simulation(state)

        self.assertEqual(person.current_node, "S")
        self.assertEqual(person.route, ["S", "A", "X"])
        self.assertNotIn("E-SD", person.route_edges)
        self.assertEqual(person.reroutes, 1)

    def test_single_narrow_route_queues_people_without_fabricating_an_alternative(self):
        state = SimulationState(building=make_single_corridor_building(), seed=1)
        state.people = [Person(f"P{i:02d}", "S", "S") for i in range(1, 4)]
        assign_group_routes(state)
        set_running(state, True)
        step_simulation(state)
        moved = sum(person.current_node == "J" for person in state.people)
        queued = [person for person in state.people if person.status == "Queued"]
        self.assertEqual(moved, 0)
        self.assertEqual(sum(person.movement_progress > 0 for person in state.people), 1)
        self.assertEqual(len(queued), 2)
        self.assertTrue(all(person.route[0] == "S" for person in queued))

    def test_live_queue_is_visible_on_the_map_and_edge_hover(self):
        state = SimulationState(building=make_single_corridor_building(), seed=5)
        state.people = [Person(f"P{i:02d}", "S", "S") for i in range(1, 4)]
        assign_group_routes(state)
        set_running(state, True)
        step_simulation(state)

        figure = render_floor_map(state, 0, "P01")
        annotation_text = {annotation.text for annotation in figure.layout.annotations}
        narrow_passage = next(trace for trace in figure.data if trace.name == "Narrow corridor")
        people_trace = next(trace for trace in figure.data if trace.name.startswith("Selected person"))

        self.assertIn("QUEUE 2", annotation_text)
        self.assertEqual(list(people_trace.text), ["P01"])
        self.assertIn("Route reservations: 3", narrow_passage.hovertext[0])
        self.assertIn("Queue: 2", narrow_passage.hovertext[0])

    def test_exit_and_passage_capacity_are_respected_each_step(self):
        state = SimulationState(building=make_single_corridor_building(exit_capacity=1), seed=2)
        # Let both people share the final passage so they reach the exit
        # together; the exit must still release only one person per beat.
        state.building.edges["E-JX"] = Edge("E-JX", "J", "X", 1, 1.0, 3)
        state.people = [Person(f"P{i:02d}", "J", "J") for i in range(1, 3)]
        assign_group_routes(state)
        set_running(state, True)
        for _ in range(12):
            step_simulation(state)
        self.assertEqual(sum(person.status == "Evacuated" for person in state.people), 1)
        self.assertEqual(sum(person.status == "Queued" for person in state.people), 1)
        self.assertEqual(sum(person.status == "Moving" for person in state.people), 0)

    def test_sensor_alarm_blocks_area_and_recalculates_routes(self):
        state = create_scenario(8, 18)
        person = next((item for item in state.people if len(item.route) >= 3), None)
        self.assertIsNotNone(person)
        target = next((node_id for node_id in person.route[1:-1] if node_id not in state.blocked_nodes), None)
        self.assertIsNotNone(target)
        sensor = next(item for item in state.sensors if item.id == f"S-{target}")
        old_reroutes = state.rerouted_total
        self.assertTrue(inject_sensor_alarm(state, sensor.id))
        self.assertIn(target, state.blocked_nodes)
        self.assertNotIn(target, person.route)
        self.assertTrue(any(event.kind == "sensor" and "ALARM" in event.message for event in state.event_log))
        self.assertGreaterEqual(state.rerouted_total, old_reroutes)

    def test_every_passage_has_a_sensor_and_multiple_distinct_alarms_can_be_triggered(self):
        state = create_scenario(6, 181, "Gas leak")
        passage_sensors = [sensor for sensor in state.sensors if sensor.target_kind == "edge"]
        self.assertEqual(len(passage_sensors), len(state.building.edges))

        first_sensor = next(
            sensor for sensor in sorted(passage_sensors, key=lambda item: item.id)
            if sensor.target_id not in state.blocked_edges
        )
        self.assertTrue(inject_sensor_alarm(state, first_sensor.id))

        second_sensor = next(
            sensor for sensor in sorted(passage_sensors, key=lambda item: item.id)
            if sensor.target_id not in state.blocked_edges
            and not any(
                hazard.target_kind == "edge" and hazard.target_id == sensor.target_id
                for hazard in state.hazards
            )
        )
        self.assertTrue(inject_sensor_alarm(state, second_sensor.id))
        alarmed_edges = [
            hazard.target_id for hazard in state.hazards if hazard.target_kind == "edge"
        ]
        self.assertIn(first_sensor.target_id, alarmed_edges)
        self.assertIn(second_sensor.target_id, alarmed_edges)
        self.assertNotEqual(first_sensor.target_id, second_sensor.target_id)
        self.assertFalse(inject_sensor_alarm(state, first_sensor.id))

        ground_sensor = next(
            sensor for sensor in state.sensors
            if sensor.metric == "ground_motion"
            and sensor.state != "Alarm"
            and sensor.target_id not in state.blocked_nodes
        )
        self.assertEqual(ground_sensor.unit, "index")
        self.assertTrue(inject_sensor_alarm(state, ground_sensor.id))
        self.assertEqual(state.hazards[-1].incident_type, "Earthquake")

    def test_midpassage_closure_keeps_progress_and_routes_from_the_safe_far_end(self):
        state = SimulationState(building=make_midroute_reroute_building(), seed=182)
        person = Person("P01", "S", "S")
        state.people = [person]
        assign_group_routes(state)
        self.assertEqual(person.route, ["S", "D", "X"])
        set_running(state, True)
        for _ in range(6):
            step_simulation(state)
        previous_progress = person.movement_progress
        previous_reroutes = person.reroutes

        state.blocked_edges.update({"E-SD", "E-DX"})
        assign_group_routes(state, reason="passage alarm")

        self.assertAlmostEqual(person.movement_progress, previous_progress)
        self.assertFalse(person.backtracking)
        self.assertEqual(person.route, ["S", "D", "A", "X"])
        self.assertEqual(person.route_edges, ["E-SD", "E-DA", "E-AX"])
        self.assertEqual(person.reroutes, previous_reroutes + 1)

        for _ in range(6):
            step_simulation(state)
        self.assertEqual(person.current_node, "D")
        self.assertEqual(person.route, ["D", "A", "X"])
        self.assertEqual(person.movement_progress, 0.0)

    def test_blocked_far_end_makes_an_inflight_person_turn_back_then_reroute(self):
        state = SimulationState(building=make_midroute_reroute_building(), seed=183)
        person = Person("P01", "S", "S")
        state.people = [person]
        assign_group_routes(state)
        set_running(state, True)
        for _ in range(6):
            step_simulation(state)
        previous_progress = person.movement_progress

        state.blocked_nodes.add("D")
        assign_group_routes(state, reason="junction alarm")
        self.assertTrue(person.backtracking)
        self.assertAlmostEqual(person.movement_progress, previous_progress)

        for _ in range(6):
            step_simulation(state)

        self.assertEqual(person.current_node, "S")
        self.assertFalse(person.backtracking)
        self.assertEqual(person.movement_progress, 0.0)
        self.assertEqual(person.route, ["S", "A", "X"])
        self.assertEqual(person.route_edges, ["E-SA", "E-AX"])
        self.assertGreaterEqual(person.reroutes, 1)

    def test_hazard_intensity_grows_expands_the_area_and_updates_sensor(self):
        state = create_scenario(8, 18, "Fire / smoke")
        hazard = state.hazards[0]
        hazard.intensity = 34.0
        hazard.growth_per_tick = 2.0
        hazard.spread_stage = 0
        previous_caution_nodes = set(state.caution_nodes)

        step_simulation(state)

        self.assertEqual(hazard.intensity, 36.0)
        self.assertEqual(hazard.level, "Elevated")
        self.assertEqual(hazard.spread_stage, 1)
        self.assertGreater(len(state.caution_nodes), len(previous_caution_nodes))
        sensor = next(
            item for item in state.sensors
            if item.target_id == hazard.target_id and item.target_kind == hazard.target_kind
        )
        self.assertEqual(sensor.metric, "smoke")
        self.assertGreater(sensor.reading, 35.0)
        self.assertEqual(sensor.state, "Warning")
        self.assertEqual(state.last_replan_tick, state.tick)
        self.assertTrue(any(event.kind == "hazard" and "affected area expanded" in event.message for event in state.event_log))

        hazard.intensity = 59.0
        hazard.growth_per_tick = 2.0
        step_simulation(state)
        self.assertEqual(hazard.spread_stage, 2)
        self.assertEqual(len(hazard.spread_edges), 1)
        self.assertIn(hazard.spread_edges[0], state.blocked_edges)

    def test_no_safe_route_is_reported_as_assistance(self):
        state = SimulationState(building=make_single_corridor_building(), seed=3)
        state.people = [Person("P01", "S", "S")]
        state.blocked_edges = {"E-SJ", "E-JX"}
        assign_group_routes(state)
        self.assertEqual(state.people[0].status, "Needs Assistance")
        self.assertEqual(state.people[0].route, [])
        self.assertTrue(any(event.kind == "assistance" for event in state.event_log))

    def test_event_history_is_bounded_and_ordered(self):
        state = SimulationState(building=build_sample_building(), seed=4)
        for tick in range(250):
            state.tick = tick
            log_event(state, "test", f"entry {tick}")
        self.assertEqual(len(state.event_log), 200)
        ticks = [event.tick for event in state.event_log]
        self.assertEqual(ticks, sorted(ticks))
        self.assertEqual(state.event_log[0].tick, 50)


if __name__ == "__main__":
    unittest.main()
