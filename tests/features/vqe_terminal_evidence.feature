Feature: VQE terminal evidence

  Scenario: Expired attempt is marked once before the next run starts
    Given a prior VQE attempt passed the configured timeout without a terminal event
    When two later dry-run VQE invocations process the history
    Then one unknown marker with the prior attempt id precedes the new run start

  Scenario: Recent and already-terminal attempts are not marked missing
    Given VQE history has an expired attempt plus recent, completed, and marked attempts
    When a later dry-run VQE invocation processes the history
    Then only the eligible expired attempt receives a new marker

  Scenario: Older unknown outcome stays per-attempt in the sync panel
    Given VQE history has an unknown older attempt and a newer running attempt
    When the existing VQE sync panel is rendered
    Then the older attempt is unknown while the headline summarizes the newer attempt
    And the panel does not attribute a cause or claim provider cancellation