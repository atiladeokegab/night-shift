// Let them watch (#291): the commentators see the shared tab. One frame every EVERY_MS, scaled to WIDTH px
// wide and sent as a JPEG; nothing is kept here. Sharing stops at once when the viewer or Chrome ends it.
export const EVERY_MS = 4000
export const WIDTH = 512

export type Media = Pick<MediaDevices, 'getDisplayMedia'>
type Frame = CanvasImageSource & { videoWidth: number; videoHeight: number }

// Chrome asks to share this tab first (preferCurrentTab and selfBrowserSurface are Chrome's own options).
export const SHARE = { video: true, preferCurrentTab: true, selfBrowserSurface: 'include' } as DisplayMediaStreamOptions

// No screen sharing (most phones, older browsers): no button.
export const canWatch = (media: Partial<Media> | undefined): media is Media => typeof media?.getDisplayMedia === 'function'

// The frame on screen as base64 JPEG, WIDTH px wide; null before the picture has a size.
export function grab(video: Frame, canvas: HTMLCanvasElement): string | null {
  const { videoWidth: w, videoHeight: h } = video
  if (!w || !h) return null
  canvas.width = WIDTH
  canvas.height = Math.round((h * WIDTH) / w)
  canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
  const url = canvas.toDataURL('image/jpeg', 0.7)
  const head = 'data:image/jpeg;base64,'
  return url.startsWith(head) ? url.slice(head.length) : null
}

// Share the tab and send a frame now and every `every` ms. `send` says false when the server takes no more
// (the replay is over), and a send still in flight skips the next frame. Throws if the viewer says no.
// The returned stop ends the sharing; `onEnd` runs once, however it ends.
export async function watch(media: Media, send: (image: string) => Promise<boolean>, onEnd: () => void,
  make: (tag: 'video' | 'canvas') => HTMLElement = (tag) => document.createElement(tag), every = EVERY_MS,
  alive: () => boolean = () => true): Promise<() => void> {
  const stream = await media.getDisplayMedia(SHARE)
  const video = make('video') as HTMLVideoElement
  const canvas = make('canvas') as HTMLCanvasElement
  let timer: ReturnType<typeof setInterval> | undefined
  let busy = false
  let over = false
  const stop = () => {
    if (over) return
    over = true
    clearInterval(timer)
    stream.getTracks().forEach((t) => t.stop())
    video.srcObject = null
    onEnd()
  }
  stream.getVideoTracks().forEach((t) => t.addEventListener('ended', stop)) // Chrome's own "Stop sharing"
  const tick = async () => {
    if (busy || over) return
    const image = grab(video, canvas)
    if (!image) return
    busy = true
    try {
      if (!(await send(image))) stop()
    } finally {
      busy = false
    }
  }
  video.muted = true
  video.srcObject = stream
  try {
    await video.play()
  } catch {
    stop()
    return stop
  }
  if (!alive()) stop() // the page went while Chrome asked: the share ends at once, no frame sent
  if (!over) {
    timer = setInterval(() => void tick(), every)
    void tick()
  }
  return stop
}
