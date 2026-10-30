// Local syntax checks; separate classic scripts may share global variables.
export default [{
  files: ['**/*.js', '**/*.mjs', '**/*.cjs'],
  languageOptions: {ecmaVersion: 'latest', sourceType: 'module'},
  rules: {'no-dupe-args': 'error', 'no-dupe-keys': 'error', 'no-unreachable': 'error'},
}];
