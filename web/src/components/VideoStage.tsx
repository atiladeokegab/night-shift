interface Props {
  youtubeId?: string
  label: string
}

// The stage (PRD v2, A-6.1@2): the match's official highlights, embedded and muted, playing behind
// the commentary. Mounted when a replay starts, so the video starts with it; the server times each
// moment to the video (A-6.4@1), so the page never holds lines back itself.
export function VideoStage({ youtubeId, label }: Props) {
  if (!youtubeId) {
    return <div className="video empty">No highlights video for this match yet.</div>
  }
  const params = new URLSearchParams({
    autoplay: '1', mute: '1', controls: '0', playsinline: '1', rel: '0', modestbranding: '1', disablekb: '1',
  })
  return (
    <div className="video">
      <iframe
        src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(youtubeId)}?${params}`}
        title={`${label}: official highlights`}
        allow="autoplay; encrypted-media; picture-in-picture"
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </div>
  )
}
