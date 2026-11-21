# SPEC-00 — Overview

> **Status:** v1 (2026-11-01) · **Owner of:** glossary, global conventions, milestone order
> **Read with:** [IDEA](../IDEA.md)

## 1. Purpose
Lendly lets volunteers lend books and remind members.

## 2. Glossary
A *loan* ties one *document* (a catalogue entry) to one member for 14 days.

## 6. Global conventions

### 6.1 Naming
Tables are plural snake_case; IDs are UUIDs.

### 6.2 Errors
Every error has a `code` and a `message` ([SPEC-08](SPEC-08-api-contract.md)).

## 8. Acceptance checks

1. The repository builds from a clean checkout.
2. Every table in [SPEC-02](SPEC-02-database-schema.md) exists after migrations.
