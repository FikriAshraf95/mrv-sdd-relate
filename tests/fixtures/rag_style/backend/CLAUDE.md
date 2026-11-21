# backend/CLAUDE.md

Backend rules for the lending API.

- Every table change follows [SPEC-02](../docs/specs/SPEC-02-database-schema.md).
- Endpoint shapes are owned by [SPEC-08 §4.6](../docs/specs/SPEC-08-api-contract.md#46-renew-a-loan).
- Never write to `loans` outside the service layer.
