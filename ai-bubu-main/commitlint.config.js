export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'scope-enum': [
      2,
      'always',
      ['app', 'site', 'skin', 'monitor', 'social', 'i18n', 'ci', 'deps'],
    ],
    'scope-empty': [1, 'never'],
    'subject-max-length': [2, 'always', 72],
  },
}
