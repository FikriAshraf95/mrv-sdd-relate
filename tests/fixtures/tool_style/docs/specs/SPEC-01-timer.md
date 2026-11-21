# SPEC-01 — Timer

> **Status:** v1 (2026-11-02) · **Owner of:** brew timing
> **Feature:** Brewing · **Domain:** Tea · **Implements:** `src/kettle/**` · **Tables:** brews, teas

## 1. Brewing

A brew has a tea and a steep time in seconds.

## 2. Teas

Each tea has a default steep time. See `src/kettle/brew.py`.

## 3. Acceptance checks

1. A green tea brew defaults to 120 seconds.
2. A black tea brew defaults to 240 seconds.
3. A brew can be paused and resumed.
