// Loads the YouTube IFrame Player API once, for the stage and the wall's tiles.
// The IFrame API script defines window.YT and calls onYouTubeIframeAPIReady once; load it once.
let api: Promise<typeof YT> | null = null

export function loadYouTube(): Promise<typeof YT> {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  api ??= new Promise((resolve) => {
    const before = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      before?.()
      resolve(window.YT!)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    document.head.appendChild(script)
  })
  return api
}
