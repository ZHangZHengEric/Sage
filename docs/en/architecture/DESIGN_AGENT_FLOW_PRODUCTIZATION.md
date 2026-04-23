---
layout: default
title: AgentFlow Productization Proposal
parent: Architecture
nav_order: 99
description: "A design proposal for turning AgentFlow into a true agent-flow runtime"
lang: en
ref: design-agent-flow-productization
---

{% include lang_switcher.html %}

# AgentFlow Productization Proposal

> Status: design draft, not implemented

This page mirrors the Chinese design note and keeps the architecture tree identical across both languages.

## Target

The proposal is to evolve AgentFlow into a runtime where every AI node is a first-class agent, while still keeping the graph:

- serializable
- resettable
- inspectable
- reusable

## Core Ideas

- make each AI step explicit
- keep node configuration persistent
- let a graph represent both orchestration and execution boundaries
- keep the runtime compatible with the existing Sage session model

## Why It Matters

This direction makes the flow layer easier to explain, easier to inspect, and easier to extend for production scenarios.

