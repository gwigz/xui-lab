# Fixtures

Fixtures will describe deterministic viewer state such as inventory folders,
items, agent identity, avatar state, and cached names. A fixture must use fixed
identifiers and must not require a network connection.

The runtime adapter must load fixture data into the fork's real models. A
fixture must not replace a production model or copy its permission rules.
