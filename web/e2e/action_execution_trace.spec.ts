import { expect, test } from '@playwright/test'

test('action execution trace renders in conversation thread when task has steps', async ({ page }) => {
  // Mock thread endpoint with simulated Hermes/OpenClaw desktop automation task
  await page.route('**/api/threads', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        threads: [
          {
            id: 'conv_hermes_demo',
            title: 'Open Spotify and search Harry',
            created_at: Date.now(),
            updated_at: Date.now(),
            agent_id: null,
            task_count: 1,
            last_goal: 'open spotify and search harry',
          },
        ],
      }),
    })
  })

  await page.route('**/api/threads/conv_hermes_demo', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        thread: {
          id: 'conv_hermes_demo',
          title: 'Open Spotify and search Harry',
          created_at: Date.now(),
          updated_at: Date.now(),
        },
        messages: [
          {
            id: 'm1',
            conversation_id: 'conv_hermes_demo',
            role: 'user',
            content: 'open spotify and search harry',
            created_at: Date.now() - 5000,
          },
        ],
        tasks: [
          {
            id: 't_demo_1',
            conversation_id: 'conv_hermes_demo',
            goal: 'open spotify and search harry',
            state: 'DONE',
            outcome: 'success',
            target: 'host',
            answer: 'Spotify opened, search query "harry" entered, and results displayed on screen.',
            created_at: Date.now() - 5000,
            updated_at: Date.now(),
            steps: [
              {
                id: 's1',
                tool: 'computer.open_app',
                status: 'success',
                args: { name: 'Spotify' },
                output: 'Spotify opened and activated',
              },
              {
                id: 's2',
                tool: 'computer.type',
                status: 'success',
                args: { text: 'harry' },
                output: 'Typed 5 characters',
              },
              {
                id: 's3',
                tool: 'computer.press',
                status: 'success',
                args: { key: 'return' },
                output: 'Key return dispatched',
              },
              {
                id: 's4',
                tool: 'computer.observe',
                status: 'success',
                args: {},
                output: 'Captured active frame',
              },
            ],
          },
        ],
      }),
    })
  })

  await page.goto('/')

  // Click on the conversation thread in the list or navigate to it
  const threadItem = page.getByText('Open Spotify and search Harry').first()
  await expect(threadItem).toBeVisible({ timeout: 5000 })
  await threadItem.click()

  // Verify conversation view opens
  await expect(page.locator('.chat-bubble-user')).toContainText('open spotify and search harry')

  // Verify Execution Trace is rendered with 4 actions
  await expect(page.getByText(/Execution Trace \(4 actions\)/i)).toBeVisible()

  // Verify individual tool actions appear
  await expect(page.getByText('computer.open_app')).toBeVisible()
  await expect(page.getByText('computer.type')).toBeVisible()
  await expect(page.getByText('computer.press')).toBeVisible()
  await expect(page.getByText('computer.observe')).toBeVisible()

  // Verify parameters appear
  await expect(page.getByText('app: "Spotify"')).toBeVisible()
  await expect(page.getByText('type: "harry"')).toBeVisible()
  await expect(page.getByText('key: "return"')).toBeVisible()

  // Verify final verified answer
  await expect(page.getByText('Spotify opened, search query "harry" entered')).toBeVisible()
})
