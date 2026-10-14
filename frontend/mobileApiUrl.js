export function validateMobileApiBaseUrl(value) {
  const configuredValue = typeof value === 'string' ? value.trim() : ''
  if (!configuredValue) {
    throw new Error(
      'Set VITE_API_BASE_URL to an absolute public HTTPS backend URL before building the mobile app.',
    )
  }

  let apiUrl

  try {
    apiUrl = new URL(configuredValue)
  } catch {
    throw new Error(
      'Set VITE_API_BASE_URL to an absolute public HTTPS backend URL before building the mobile app.',
    )
  }

  if (
    apiUrl.protocol !== 'https:' ||
    !apiUrl.hostname ||
    apiUrl.username ||
    apiUrl.password ||
    apiUrl.search ||
    apiUrl.hash
  ) {
    throw new Error(
      'Set VITE_API_BASE_URL to an absolute public HTTPS backend URL before building the mobile app.',
    )
  }

  return apiUrl.toString().replace(/\/+$/, '')
}
