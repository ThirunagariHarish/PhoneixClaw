/**
 * DataTable: table with optional loading and empty state. M1.5 composite.
 */
import * as React from 'react'
import { cn } from '@/lib/utils'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'

export interface Column<T> {
  id: string
  header: string
  cell?: (row: T) => React.ReactNode
  accessor?: keyof T | ((row: T) => unknown)
}

export interface DataTableProps<T> {
  columns: Column<T>[]
  data: T[]
  keyField?: keyof T
  isLoading?: boolean
  emptyMessage?: string
  className?: string
}

export function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  keyField = 'id' as keyof T,
  isLoading,
  emptyMessage = 'No data',
  className,
}: DataTableProps<T>) {
  const key = typeof keyField === 'string' ? keyField : 'id'
  return (
    <div className={cn('rounded-md border', className)}>
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((col) => (
              <TableHead key={col.id}>{col.header}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading
            ? Array.from({ length: 3 }).map((_, i) => (
                <TableRow key={i}>
                  {columns.map((col) => (
                    <TableCell key={col.id}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : data.length === 0
              ? (
                <TableRow>
                  <TableCell colSpan={columns.length} className="text-center text-muted-foreground py-8">
                    {emptyMessage}
                  </TableCell>
                </TableRow>
                )
              : data.map((row) => (
                <TableRow key={String(row[key])}>
                  {columns.map((col) => (
                    <TableCell key={col.id}>
                      {col.cell
                        ? col.cell(row)
                        : String(col.accessor ? (typeof col.accessor === 'function' ? (col.accessor as (r: T) => unknown)(row) : row[col.accessor]) : '')}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
        </TableBody>
      </Table>
    </div>
  )
}
