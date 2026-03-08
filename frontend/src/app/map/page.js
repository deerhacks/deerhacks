import dynamic from 'next/dynamic'

export const metadata = {
  title: 'Map — Locatr',
  description: 'Explore locations with Locatr',
}

const MapComponent = dynamic(() => import('./MapComponent'), { ssr: false })

export default function MapPage() {
  return <MapComponent />
}
