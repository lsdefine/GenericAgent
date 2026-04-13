export function initLangToggle() {
  const toggle = document.getElementById('langToggle')
  if (!toggle) return
  const parts = window.location.pathname.split('/')
  const currentLocale = parts[1] === 'en' ? 'en' : 'zh'
  toggle.textContent = currentLocale === 'en' ? '中' : 'EN'
  toggle.addEventListener('click', () => {
    parts[1] = currentLocale === 'en' ? 'zh' : 'en'
    window.location.href = parts.join('/')
  })
}
