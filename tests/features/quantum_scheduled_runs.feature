Feature: Quantum scheduled run outcomes

  Scenario: Monthly policies remain UTC across seasonal time changes
    Given the configured monthly Quantum schedules
    When next runs are calculated after a summer date
    Then cache fill, Shor, and VQE resolve to their configured UTC instants

  Scenario: Cache fill records success only after verified bits are persisted
    Given a successful cache-fill provider result and an isolated Quantum database
    When the cache-fill runner completes
    Then the cache has a backup and an attempt-correlated successful terminal event

  Scenario: VQE reports success only when both configured molecules meet accuracy
    Given successful H2 and LiH results and an isolated Quantum database
    When the VQE scheduled runner completes
    Then one attempt-correlated successful terminal event names both molecules

  Scenario: Scheduled Shor approval still requires a successful factor result
    Given a scheduled Shor run with the policy approval and an isolated Quantum database
    When the Shor scheduled runner completes with factors 3 and 5
    Then it records an approved hardware success and exits zero