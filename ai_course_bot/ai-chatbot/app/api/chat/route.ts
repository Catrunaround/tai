import { auth } from '@/tai/utils/auth'
import { kv } from '@vercel/kv'
import { nanoid } from '@/tai/lib/utils'

export const runtime = 'edge'

export async function POST(req: Request) {
  const json = await req.json()

  const { messages, previewToken } = json
  var courseId = messages[messages.length - 1].tool_call_id

  const userId: string = (await auth())?.user.email ?? ''

  if (courseId == null || userId == '') {
    courseId = 'default'
  }

  var apiHost: string =
    courseId === 'CS 294-137'
      ? process.env['CS_294_137_BACKEND_HOST'] || 'http://0.0.0.0:9000'
      : process.env['ROAR_BACKEND_HOST'] || 'http://0.0.0.0:9000'

  const apiUrl: string = apiHost + '/api/chat/completions'

  try {
    var body = JSON.stringify({
      course: courseId,
      messages,
      temperature: 0.7,
      stream: true,
      userId: userId
    })

    const apiResponse = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: body
    })

    if (apiResponse.ok) {
      return new Response(apiResponse.body, {
        headers: { 'Content-Type': 'application/json' }
      })
    } else {
      console.log('[Route.ts] API Response Not Ok')
      return new Response('Error fetching data', { status: apiResponse.status })
    }
  } catch (error) {
    console.log('[Route.ts] Error: ', error)
    return new Response(
      'Internal Server Error; Server may be down, Please try again later',
      { headers: { 'Content-Type': 'application/json' } }
    )
  }
}
