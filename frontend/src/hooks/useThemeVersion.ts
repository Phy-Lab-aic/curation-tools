import { useEffect, useState } from 'react'

/**
 * Returns a counter that increments whenever <html>'s inline `style`
 * attribute changes. The app's theme system (App.tsx `applyTheme`) sets
 * CSS custom properties via `documentElement.style.setProperty`, so this
 * hook gives canvas-based components a dependency they can react to.
 */
export function useThemeVersion(): number {
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setVersion(v => v + 1)
    })
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style'],
    })
    return () => observer.disconnect()
  }, [])

  return version
}
