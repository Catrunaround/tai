# Query Workflow Modularization

This document describes the current refactor baseline for `/api/chat/completions`.

## Goals

- Keep existing query behavior stable while isolating fast-changing tutor logic.
- Separate orchestration from legacy implementation details.
- Add explicit STM/LTM workflow hooks without breaking existing routes.

## New Modules

- `app/query/contracts/models.py`
  - Shared context and output dataclasses used by orchestration.
- `app/query/orchestrator/query_orchestrator.py`
  - Fixed request workflow for completions.
- `app/query/workflow/request_stage.py`
  - Step 1 request preparation and validation.
- `app/query/workflow/query_stage.py`
  - Step 2 query formation + mode branch + model generation.
- `app/query/workflow/response_stage.py`
  - Step 3 stream parse/SSE emit + Step 4 memory update hooks.
- `app/query/policies/`
  - Mode policies (`RegularPolicy`, `TutorPolicy`) selected by `tutor_mode`.
- `app/query/memory/manager.py`
  - STM load/update hooks, goal-shift detection, LTM placeholder hook.
- `app/query/utils/message_cleaner.py`
  - Assistant message sanitizer.

## Runtime Flow

1. Build request context and timer.
2. Resolve mode policy (`regular` / `tutor`).
3. **Step 1 (`request_stage`)**:
   - Resolve LLM engine and optional speech-to-text.
   - Sanitize assistant history messages.
   - Validate file/practice branch inputs.
4. **Step 2 (`query_stage`)**:
   - Load STM and detect goal shift.
   - Build retrieval query and augmented prompt.
   - Branch by mode using explicit `if/else`:
     - `text_tutor`
     - `voice_tutor`
     - `text_regular`
     - `voice_regular`
   - Run model generation.
5. **Step 3 (`response_stage`)**:
   - Stream parse + SSE emit for streaming requests.
   - Non-stream JSON response for non-stream requests.
6. **Step 4 (`response_stage` + `memory manager`)**:
   - Update short-term memory after response.
   - Trigger long-term memory hook (placeholder).

## Stability Notes

- `file chat` behavior is preserved via legacy adapter path.
- RAG remains enabled by existing generation flow.
- Tutor behavior is still controlled by `tutor_mode`; this refactor only moves control boundaries.
