from collections import defaultdict, deque


def topological_sort(
    dependencies: list[list],
    return_error_msg: bool = False,
    form=None,
    item_id: int = None,
) -> list:
    """Sort dependencies in order of dependency
    - Input: dependencies = [[child, parent], [child, parent], ...]
    """

    # Step 1: Create a graph and calculate in-degrees
    graph = defaultdict(list)
    in_degree = defaultdict(int)

    for dependency in dependencies:
        child, parent = dependency
        graph[parent].append(child)
        in_degree[child] += 1

    # Step 2: Initialize a queue with nodes having in-degree of 0
    queue = deque([node for node in graph if in_degree[node] == 0])

    # Step 3: Perform topological sort
    sorted_order = []
    cycle_check = set()

    while queue:
        node = queue.popleft()
        sorted_order.append(node)
        cycle_check.add(node)

        for child in graph[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    # Step 4: Check for a cycle (if any in-degree remains non-zero)
    if len(sorted_order) != len(graph):
        cyclic_dependencies = [
            dep
            for dep in dependencies
            if dep[0] not in cycle_check or dep[1] not in cycle_check
        ]
        if return_error_msg and form and item_id:
            item_cyclic_dependencies = [
                row
                for row in cyclic_dependencies
                if str(item_id) in (row[0].split("@")[0], row[1].split("@")[0])
            ]
            form.add_error(
                "date_due_depend_id",
                "*The following date dependencies will cause recursive errors:",
            )
            for row in reversed(item_cyclic_dependencies):
                child_id = (
                    "current item"
                    if row[0].split("@")[0] == str(item_id)
                    else f"item {row[0].split('@')[0]}"
                )
                parent_id = (
                    "current item"
                    if row[1].split("@")[0] == str(item_id)
                    else f"item {row[1].split('@')[0]}"
                )
                form.add_error(
                    "date_due_depend_id",
                    f"- Field {row[0].split('@')[1].split('date_')[1]} in {child_id} depends on {row[1].split('@')[1].split('date_')[1]} in {parent_id}",
                )
            return None, True, form

        raise ValueError(
            f"The input graph has a cycle involving these dependencies: {*cyclic_dependencies,}"
        )

    return sorted_order, False, form
