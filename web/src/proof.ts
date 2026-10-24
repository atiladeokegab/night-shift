// The Proof card's "Next adapter" figure: fixes since the latest adapter against the number Mubit needs.
// Past the target it says so, rather than "66 of 25".
export function nextAdapter(toward: number, needed: number): { value: string; note: string | null } {
  if (toward < needed) return { value: `${toward} of ${needed}`, note: null }
  return { value: 'Enough', note: `${toward} fixes recorded · ${needed} needed: enough for the next adapter` }
}
