// icons.ts — the page icons (white list of pages.py PAGE_ICONS) as lucide components.

import {
  Bell, Box, Brush, CalendarDays, Camera, Clapperboard, Film, Folder, Image, Kanban, Layers, LayoutDashboard,
  ListChecks, MessageSquare, Package, Palette, Rocket, Send, Star, Users, Wrench, Zap, type LucideIcon,
} from 'lucide-react'

export const PAGE_ICONS: Record<string, LucideIcon> = {
  wrench: Wrench, film: Film, camera: Camera, clapperboard: Clapperboard, folder: Folder, box: Box, package: Package,
  layers: Layers, image: Image, brush: Brush, palette: Palette, calendar: CalendarDays, 'message-square': MessageSquare,
  users: Users, kanban: Kanban, 'layout-dashboard': LayoutDashboard, 'list-checks': ListChecks, rocket: Rocket,
  send: Send, bell: Bell, star: Star, zap: Zap,
}

export const pageIcon = (name: string | undefined): LucideIcon => PAGE_ICONS[name ?? ''] ?? Wrench
