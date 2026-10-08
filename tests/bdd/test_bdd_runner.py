from pytest_bdd import given, scenarios, then, when

scenarios("bdd_runner.feature")


@given("a deterministic collection of values", target_fixture="values")
def values() -> list[int]:
    return [1, 2, 3]


@when("the collection is totaled", target_fixture="total")
def total_values(values: list[int]) -> int:
    return sum(values)


@then("the result is 6")
def total_is_six(total: int) -> None:
    assert total == 6