import assert from 'node:assert/strict'
import test from 'node:test'

import { validateMobileApiBaseUrl } from '../mobileApiUrl.js'

test('accepts absolute HTTPS API URLs and removes trailing slashes', () => {
  assert.equal(
    validateMobileApiBaseUrl('https://api.example.com/'),
    'https://api.example.com',
  )
})

test('rejects HTTP API URLs', () => {
  assert.throws(
    () => validateMobileApiBaseUrl('http://api.example.com'),
    /absolute public HTTPS/,
  )
})

test('rejects malformed and relative API URLs', () => {
  for (const value of ['not a URL', '/api', '']) {
    assert.throws(
      () => validateMobileApiBaseUrl(value),
      /absolute public HTTPS/,
    )
  }
})

test('rejects API URLs containing credentials, query strings, or fragments', () => {
  for (const value of [
    'https://user:password@api.example.com',
    'https://api.example.com?token=value',
    'https://api.example.com#fragment',
  ]) {
    assert.throws(
      () => validateMobileApiBaseUrl(value),
      /absolute public HTTPS/,
    )
  }
})
