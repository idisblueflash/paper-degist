Feature: US18 — launch (or reuse) a dev-mode Chrome for the browser lane

  As a Claude Code session about to run the browser lane
  I want one command that brings up a dev-mode Chrome on the CDP port and prints its endpoint
  So that I stop re-deriving the launch incantation and the researcher logs in once

  Scenario: No dev-mode Chrome yet — launch one and print the endpoint
    Given no dev-mode Chrome is answering on "http://localhost:9222"
    And a Chrome binary is installed
    When browser-up brings the browser up
    Then it prints the CDP endpoint "http://localhost:9222"
    And it launches exactly one Chrome and leaves it running

  Scenario: A dev-mode Chrome is already reachable — reuse it, no second Chrome
    Given a dev-mode Chrome is already reachable on "http://localhost:9333"
    When browser-up brings the browser up
    Then it prints the CDP endpoint "http://localhost:9333"
    And it does not launch a second Chrome

  Scenario: The fixed persistent profile carries the login across runs
    Given no dev-mode Chrome is answering on "http://localhost:9222"
    And a Chrome binary is installed
    When browser-up brings the browser up against profile ".browser-profile"
    Then Chrome is launched against the persistent profile ".browser-profile"

  Scenario: No Chrome binary — a loud failure naming the missing browser
    Given no dev-mode Chrome is answering on "http://localhost:9222"
    And no Chrome binary can be found
    When browser-up tries to bring the browser up
    Then it fails loudly with a reason mentioning "Chrome"

  Scenario: The port is held by a non-debug process — a distinct loud failure
    Given the CDP port on "http://localhost:9222" is held by a non-debug process
    When browser-up tries to bring the browser up
    Then it fails loudly with a reason mentioning "port"
    And it does not launch a Chrome
