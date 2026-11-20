# Workspace instructions

## Sage v2 production releases

- A Sage v2 release on withling is complete only after the new release passes its observation window, the previous worker has safely drained, and the previous frontend and backend containers and their release images have been removed.
- Before reporting completion, verify the public routes, check that the previous containers and image references are gone, and confirm that only the current release can claim work from the shared Redis execution queue.
- Preserve shared production data and release records. Rebuild or pull the exact previous release images if a rollback is later needed.
