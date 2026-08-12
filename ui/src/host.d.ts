declare const __LENS_BUILD__: string

declare module '@kirocrew/app-sdk' {
  export function useAppApi(): {
    get<T>(path: string): Promise<T>
  }
}

declare module '@kirocrew/app-sdk/ui' {
  import type { ComponentType } from 'react'
  export const PageHeader: ComponentType<any>
  export const StatCard: ComponentType<any>
  export const Card: ComponentType<any>
  export const CardTitle: ComponentType<any>
  export const Badge: ComponentType<any>
  export const EmptyState: ComponentType<any>
  export const Skeleton: ComponentType<any>
}

declare module 'lucide-react' {
  import type { ComponentType } from 'react'
  export const ChevronRight: ComponentType<any>
  export const Check: ComponentType<any>
  export const AlertTriangle: ComponentType<any>
  export const Search: ComponentType<any>
}
