// Card artwork from docs/mockup/index.html (the designer's own SVG; no photographs or player likenesses,
// docs/design.md "References"): a night stadium with the two teams' crests. Built as a string from
// fixed numbers only (no data from the server), so it is safe to set as markup.
import type { TeamStyle } from './teams'

function rng(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function stadium(id: string, w: number, h: number, sport: string, seed: number, extra: string): string {
  const R = rng(seed), hz = h * 0.47, ph = h - hz
  let s = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><defs>
    <linearGradient id="${id}s" x2="0" y2="1"><stop offset="0" stop-color="#0B1736"/><stop offset="1" stop-color="#04060C"/></linearGradient>
    <radialGradient id="${id}g"><stop offset="0" stop-color="#F4F8FF" stop-opacity=".95"/><stop offset=".12" stop-color="#C9DAFF" stop-opacity=".4"/><stop offset="1" stop-color="#9DB8FF" stop-opacity="0"/></radialGradient>
    <linearGradient id="${id}b" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".09"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
    <linearGradient id="${id}p" x2="0" y2="1"><stop offset="0" stop-color="#1D6A3D"/><stop offset=".55" stop-color="#145430"/><stop offset="1" stop-color="#0A2E1B"/></linearGradient>
    <linearGradient id="${id}l" x2="1"><stop offset="0" stop-color="#FFB547"/><stop offset=".5" stop-color="#5B8CFF"/><stop offset="1" stop-color="#FFB547"/></linearGradient>
    <linearGradient id="${id}t" x2="0" y2="1"><stop offset="0" stop-color="#B89A6A"/><stop offset="1" stop-color="#D9BC8A"/></linearGradient>
  </defs><rect width="${w}" height="${h}" fill="url(#${id}s)"/>`
  for (const fx of [0.07, 0.3, 0.7, 0.93]) {
    const cx = w * fx, cy = h * 0.075
    s += `<polygon points="${cx - 8},${cy} ${cx + 8},${cy} ${cx + w * 0.1 * (fx < 0.5 ? 1.4 : 0.6)},${hz + ph * 0.5} ${cx - w * 0.1 * (fx < 0.5 ? 0.6 : 1.4)},${hz + ph * 0.5}" fill="url(#${id}b)"/>
      <circle cx="${cx}" cy="${cy}" r="${w * 0.17}" fill="url(#${id}g)" opacity=".7"/>`
    // The lamps at 0.3 land under the sport label on a tall card; App.css hides them there.
    s += `<g${fx === 0.3 ? ' class="by-label"' : ''}>`
    for (let r = 0; r < 2; r++) for (let c = 0; c < 4; c++) s += `<rect x="${cx - 14 + c * 7.5}" y="${cy - 6 + r * 7}" width="5" height="5" rx="1" fill="#fff"/>`
    s += '</g>'
  }
  const roof = (x: number) => h * 0.21 - h * 0.07 * 4 * (x / w) * (1 - x / w)
  s += `<path d="M0 ${h * 0.21} Q${w / 2} ${h * 0.07} ${w} ${h * 0.21} L${w} ${hz} L0 ${hz} Z" fill="#0A1020"/>`
  for (const k of [0.3, 0.55, 0.8]) {
    s += `<path d="M0 ${h * 0.21 + (hz - h * 0.21) * k} Q${w / 2} ${h * 0.07 + (hz - h * 0.07) * k} ${w} ${h * 0.21 + (hz - h * 0.21) * k}" stroke="#fff" stroke-opacity=".05" fill="none"/>`
  }
  const crowd = ['#FFFFFF', '#FFE2B0', '#A9C6FF', '#FFB547', ...(sport === 'football' ? ['#E8414C', '#FFFFFF'] : ['#4FA3FF', '#2FBF71'])]
  for (let i = 0; i < 260; i++) {
    const x = R() * w, top = roof(x) + 10, y = top + R() * (hz - top - 14)
    s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(0.7 + R() * 2.1).toFixed(2)}" fill="${crowd[(R() * crowd.length) | 0]}" opacity="${(0.1 + R() * 0.45).toFixed(2)}"/>`
  }
  s += `<rect y="${hz - h * 0.026}" width="${w}" height="${h * 0.022}" fill="url(#${id}l)" opacity=".22"/>
    <rect y="${hz}" width="${w}" height="${ph}" fill="url(#${id}p)"/>`
  for (let i = 0; i < 10; i += 2) {
    const y0 = hz + ph * (i / 10) ** 1.5, y1 = hz + ph * ((i + 1) / 10) ** 1.5
    s += `<rect y="${y0}" width="${w}" height="${y1 - y0}" fill="#fff" opacity=".035"/>`
  }
  if (sport === 'football') {
    s += `<g stroke="#fff" stroke-opacity=".45" stroke-width="${w / 800}" fill="none">
      <line x1="0" y1="${hz + 5}" x2="${w}" y2="${hz + 5}"/><line x1="${w * 0.5}" y1="${hz + 5}" x2="${w * 0.43}" y2="${h}"/>
      <ellipse cx="${w * 0.475}" cy="${hz + ph * 0.42}" rx="${w * 0.15}" ry="${ph * 0.17}"/>
      <path d="M${w} ${hz + ph * 0.1} L${w * 0.86} ${hz + ph * 0.1} L${w * 0.8} ${hz + ph * 0.62} L${w} ${hz + ph * 0.62}"/></g>`
  } else if (sport === 'cricket') {
    const t = hz + ph * 0.06, b = hz + ph * 0.52, cx = w * 0.5
    s += `<ellipse cx="${cx}" cy="${hz + ph * 0.56}" rx="${w * 0.66}" ry="${ph * 0.62}" stroke="#fff" stroke-opacity=".3" fill="none" stroke-width="${w / 600}"/>
      <ellipse cx="${cx}" cy="${hz + ph * 0.5}" rx="${w * 0.3}" ry="${ph * 0.36}" stroke="#fff" stroke-opacity=".18" stroke-dasharray="6 8" fill="none"/>
      <polygon points="${cx - w * 0.018},${t} ${cx + w * 0.018},${t} ${cx + w * 0.04},${b} ${cx - w * 0.04},${b}" fill="url(#${id}t)" opacity=".85"/>
      <g stroke="#fff" stroke-opacity=".8" stroke-width="${w / 900}"><line x1="${cx - w * 0.03}" y1="${t + ph * 0.04}" x2="${cx + w * 0.03}" y2="${t + ph * 0.04}"/><line x1="${cx - w * 0.055}" y1="${b - ph * 0.07}" x2="${cx + w * 0.055}" y2="${b - ph * 0.07}"/></g>
      <g fill="#F2E6CC">${[-1, 0, 1].map((k) => `<rect x="${cx + k * w * 0.004 - 1}" y="${t - ph * 0.03}" width="2" height="${ph * 0.03}"/><rect x="${cx + k * w * 0.007 - 1.5}" y="${b - ph * 0.1}" width="3" height="${ph * 0.05}"/>`).join('')}</g>`
  }
  return s + extra + '</svg>'
}

const SHADE = '<defs><linearGradient id="shade" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".3"/></linearGradient></defs>'

function crest(x: number, y: number, team: TeamStyle): string {
  const shield = 'M0 8 Q60 -8 120 8 V78 Q120 138 60 162 Q0 138 0 78 Z'
  const code = team.code.replace(/[^A-Z]/g, '').slice(0, 3)
  return `<g transform="translate(${x} ${y})"><ellipse cx="60" cy="80" rx="100" ry="100" fill="${team.color}" opacity=".3" filter="blur(30px)"/>
    <path d="${shield}" fill="${team.color}"/><path d="${shield}" fill="url(#shade)"/>
    <path d="M10 16 Q60 2 110 16 V78 Q110 130 60 151 Q10 130 10 78 Z" fill="none" stroke="${team.ink}" stroke-opacity=".5" stroke-width="2"/>
    <text x="60" y="94" text-anchor="middle" font-family="Outfit, sans-serif" font-weight="700" font-size="36" fill="${team.ink}">${code}</text></g>`
}

const cache = new Map<string, string>()

// The card's artwork for a match: the stadium (pitch markings for football and cricket only; the design
// has no art for basketball or f1 yet) and the crests, both sides' or a lone one (an f1 driver's). The
// crests are their own svg, placed by App.css: inside the stadium's slice a tall card cropped them.
export function cardArt(sport: string, home: TeamStyle, away: TeamStyle | null): string {
  const key = `${sport}:${home.code}:${away?.code}`
  if (!cache.has(key)) {
    const id = sport === 'football' ? 'cf' : 'cc'
    const crests = away ? crest(0, 0, home) + crest(140, 0, away) : crest(140, 0, home)
    cache.set(key, stadium(id + sport, 800, 500, sport, sport === 'football' ? 11 : 23, '')
      + `<svg class="crests" viewBox="0 0 260 162" aria-hidden="true">${SHADE}${crests}</svg>`)
  }
  return cache.get(key)!
}
