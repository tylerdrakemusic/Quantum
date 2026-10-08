Feature: BDD runner smoke
  Scenario: pytest executes bound steps from a feature file
    Given a deterministic collection of values
    When the collection is totaled
    Then the result is 6