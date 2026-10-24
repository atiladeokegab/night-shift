// The Proof card's "Next adapter" figure: fixes since the latest adapter against the number Mubit needs.
export function nextAdapter(toward: number, needed: number): { value: string; note: string | null } {
  return { value: `${toward} of ${needed}`, note: null }
}
