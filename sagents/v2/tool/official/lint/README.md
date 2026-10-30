# Standard lint runtime

Install Node.js, then run `npm ci --ignore-scripts --no-audit --no-fund` here.
Dependencies are pinned by package-lock.json. No packages are downloaded during a check.

RSI automatically selects this runtime for target Agents with read_lints. The host
freezes its files and Node executable at admission. The launcher ignores workspace
ESLint configuration and uses the fixed rules here. Checks are read-only operations
but run as bounded processes inside the isolated target workspace without networking.
Do not modify dependencies during a running experiment.

HTML/CSS use Sage's in-process parsers. JavaScript checks use ESLint. This launcher
currently supports POSIX hosts; it does not claim Windows runtime support.
