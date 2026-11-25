import { expect, test } from '@playwright/test'

async function signIn(page, username) {
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(process.env.RESEARCHHUB_FIXTURE_PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
}

test('mobile project, execution, results, funding and audit', async ({ page, request }) => {
  const suffix = Date.now()
  await page.goto('/')
  await page.getByLabel('Username').fill('unknown-fixture-user')
  await page.getByLabel('Password').fill('wrong fixture password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid credentials')
  await signIn(page, 'fixture-pi')
  const project = page.getByRole('combobox', { name: 'Project' })
  await project.selectOption({ label: 'Secondary fixture' })
  await expect(page.getByText('researcher', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Datasets' }).click()
  await expect(page.getByText('No datasets registered')).toBeVisible()
  await project.selectOption({ label: 'Primary fixture' })
  await expect(page.getByText('pi', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Synthetic fixture' }).click()
  await expect(page.getByRole('button', { name: 'Download dataset' })).toBeVisible()

  await page.getByRole('button', { name: 'Jobs', exact: true }).click()
  await page.getByRole('button', { name: 'Submit summary job' }).click()
  await expect.poll(async () => {
    const refresh = page.getByRole('button', { name: 'Refresh' })
    await refresh.click()
    await expect(refresh).toBeEnabled()
    return page.getByText('SUCCEEDED', { exact: true }).count()
  }, { timeout: 15000 }).toBeGreaterThan(0)
  const succeeded = page.getByRole('row').filter({ hasText: 'SUCCEEDED' }).first()
  await succeeded.getByRole('button', { name: 'Details' }).click()
  await expect(page.locator('pre')).toContainText('result_committed')
  const download = page.waitForEvent('download')
  await succeeded.getByRole('button', { name: 'Manifest' }).click()
  expect((await download).suggestedFilename()).toBe('manifest.json')

  await page.getByRole('button', { name: 'Workflows', exact: true }).click()
  await page.getByRole('button', { name: 'Run summary template' }).click()
  await expect.poll(async () => {
    const refresh = page.getByRole('button', { name: 'Refresh' })
    await refresh.click()
    await expect(refresh).toBeEnabled()
    return page.getByText('SUCCEEDED', { exact: true }).count()
  }, { timeout: 15000 }).toBeGreaterThanOrEqual(4)

  await page.getByRole('button', { name: 'Funding' }).click()
  await page.getByLabel('Amount').fill('100')
  await page.getByLabel('Purpose').fill('Lab allocation ' + suffix)
  await page.getByRole('button', { name: 'Request funds' }).click()
  await expect(page.getByText('Lab allocation ' + suffix, { exact: false })).toContainText('PENDING')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await signIn(page, 'fixture-finance')
  await page.getByRole('button', { name: 'Funding' }).click()
  const item = page.getByRole('listitem').filter({ hasText: 'Lab allocation ' + suffix })
  await item.getByRole('button', { name: 'Approve' }).click()
  await expect(item).toContainText('APPROVED')
  await page.getByRole('button', { name: 'Audit' }).click()
  await expect(page.locator('pre')).toContainText('funding_reviewed')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  expect((await request.get('/api/readyz')).ok()).toBeTruthy()
})

test('administrator creates a project and account with one-time password rotation', async ({ page }) => {
  const suffix = Date.now().toString()
  const projectName = 'Managed fixture ' + suffix
  const username = 'managed-fixture-' + suffix
  const replacementPassword = 'browser-rotated-' + suffix
  await page.goto('/')
  await signIn(page, 'fixture-admin')
  await page.getByRole('button', { name: 'System health' }).click()
  await expect(page.locator('pre')).toContainText('job_queue_wait_ms')
  await expect(page.locator('pre')).toContainText('job_execution_ms')
  await expect(page.locator('pre')).toContainText('http_requests')
  await page.getByRole('button', { name: 'Administration' }).click()
  await page.locator('select[name="organization"]').selectOption({ label: 'Fixture Lab' })
  await page.locator('input[name="name"]').fill(projectName)
  await page.locator('input[name="budget"]').fill('1200')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await page.getByRole('button', { name: 'Administration' }).click()
  await page.locator('input[name="username"]').fill(username)
  await page.getByRole('button', { name: 'Create account' }).click()
  const temporaryCredentials = await page.locator('code').textContent()
  expect(temporaryCredentials).toContain(username + ': ')
  const temporaryPassword = temporaryCredentials.split(username + ': ')[1]
  expect(temporaryPassword.length).toBeGreaterThanOrEqual(12)
  await page.getByRole('button', { name: 'Dismiss' }).click()
  await page.getByRole('button', { name: 'Members' }).click()
  await page.locator('input[name="username"]').fill(username)
  await page.locator('select[name="role"]').selectOption('researcher')
  await page.getByRole('button', { name: 'Add member' }).click()
  await expect(page.getByText(username, { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(temporaryPassword)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByLabel('New password')).toBeVisible()
  await page.getByLabel('New password').fill(replacementPassword)
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await expect(page.getByText('researcher', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Administration' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Members' })).toHaveCount(0)
})

test('mobile research workflow publishes artifacts and replays notifications', async ({ page }) => {
  test.setTimeout(60000)
  const datasetName = 'Synthetic mobility ' + Date.now()
  await page.goto('/')
  await signIn(page, 'fixture-pi')
  await page.getByRole('button', { name: 'Datasets', exact: true }).click()
  await page.getByLabel('Dataset name').fill(datasetName)
  await page.getByRole('button', { name: 'Register dataset' }).click()
  await page.getByRole('button', { name: datasetName }).click()
  await page.getByLabel('CSV file').setInputFiles({
    name: 'synthetic.csv', mimeType: 'text/csv',
    buffer: Buffer.from('participant_id,timestamp_utc,latitude,longitude,steps\n' +
      'synthetic01,2025-01-01T00:00:00Z,0,0,10\n' +
      'synthetic01,2025-01-01T00:10:00Z,0.001,0,20\n'),
  })
  await page.getByRole('button', { name: 'Upload new version' }).click()
  await expect(page.getByRole('button', { name: 'Download dataset' })).toBeVisible()

  await page.getByRole('button', { name: 'Workflows', exact: true }).click()
  await page.getByLabel('Discipline').selectOption('mobility')
  await page.getByRole('combobox', { name: 'Dataset', exact: true }).selectOption({ label: datasetName })
  const requestPromise = page.waitForRequest((request) =>
    request.method() === 'POST' && request.url().endsWith('/research-workflows'))
  const responsePromise = page.waitForResponse((response) =>
    response.request().method() === 'POST' && response.url().endsWith('/research-workflows'))
  await page.getByRole('button', { name: 'Start research workflow' }).click()
  const submittedRequest = await requestPromise
  const response = await responsePromise
  if (!response.ok()) {
    throw new Error(`Research workflow submission failed: payload=${JSON.stringify(submittedRequest.postDataJSON())} HTTP ${response.status()} ${await response.text()}`)
  }
  const { id } = await response.json()
  const mobility = page.locator('article[data-run-id="' + id + '"]')
  await expect.poll(async () => {
    const refresh = page.getByRole('button', { name: 'Refresh' })
    await refresh.click()
    await expect(refresh).toBeEnabled()
    return mobility.locator('h2').textContent()
  }, { timeout: 25000 }).toContain('SUCCEEDED')
  await mobility.getByRole('button', { name: 'Provenance', exact: true }).click()
  await expect(page.locator('pre')).toContainText('output_sha256')

  await page.getByRole('button', { name: 'Artifacts', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Scientific artifact registry' })).toBeVisible()
  await expect(page.getByRole('cell', { name: /Dataset v1/ }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Resources', exact: true }).click()
  await expect(page.getByText('Logical CPU units')).toBeVisible()

  await page.getByRole('button', { name: 'Notifications', exact: true }).click()
  const message = 'Synthetic project update ' + Date.now()
  await page.getByLabel('Project announcement').fill(message)
  await page.getByRole('button', { name: 'Post announcement' }).click()
  const notice = page.getByRole('listitem').filter({ hasText: message })
  await expect(notice).toBeVisible({ timeout: 12000 })
  await notice.getByRole('button', { name: 'Mark read' }).click()
  await expect(notice.getByRole('button', { name: 'Mark unread' })).toBeVisible()
  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  await page.getByRole('button', { name: 'Notifications', exact: true }).click()
  await expect(notice.getByRole('button', { name: 'Mark unread' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
