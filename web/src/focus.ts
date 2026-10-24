import { useEffect, type RefObject } from 'react'

// #170: a sheet takes the keyboard's focus when it opens and gives it back to what opened it on close,
// so a screen reader lands inside the dialog it announces and returns to where the viewer was.
export function useSheetFocus(sheet: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null
    sheet.current?.querySelector<HTMLElement>('button:not(:disabled), textarea, input:not(:disabled)')?.focus()
    return () => back?.focus()
  }, [sheet])
}
