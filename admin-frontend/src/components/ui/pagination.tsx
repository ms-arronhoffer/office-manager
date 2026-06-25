import * as React from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "./button"
import { cn } from "@/lib/utils"

interface PaginationProps {
  currentPageIndex: number
  pagesCount: number
  onChangePageIndex: (index: number) => void
  disabled?: boolean
}

export function Pagination({
  currentPageIndex,
  pagesCount,
  onChangePageIndex,
  disabled,
}: PaginationProps) {
  return (
    <div className="flex items-center justify-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChangePageIndex(Math.max(0, currentPageIndex - 1))}
        disabled={disabled || currentPageIndex === 0}
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </Button>
      <span className="text-sm text-slate-600">
        Page {currentPageIndex + 1} of {pagesCount}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChangePageIndex(Math.min(pagesCount - 1, currentPageIndex + 1))}
        disabled={disabled || currentPageIndex >= pagesCount - 1}
      >
        Next
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  )
}
