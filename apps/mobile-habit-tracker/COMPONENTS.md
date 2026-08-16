# Components

12 component(s) in this app. Each is self-contained and props-driven — reuse it in another feature by importing it and passing its props. Generated from `src/components/` by ADF.

## `HabitForm` — `src/components/HabitForm.tsx`

| prop | type | required |
|---|---|:--:|
| `onSubmit` | `(name: string) => void | Promise<void>` | ✓ |

## `HabitList` — `src/components/HabitList.tsx`

| prop | type | required |
|---|---|:--:|
| `habits` | `Habit[]` | ✓ |
| `onOpen` | `(habit: Habit) => void` | ✓ |
| `onDelete` | `(id: number) => void` | ✓ |

## `Badge` — `src/components/ui/Badge.tsx`

| prop | type | required |
|---|---|:--:|
| `label` | `string | number` | ✓ |
| `tone` | `'primary' | 'success' | 'danger' | 'warning'` | — |

## `Button` — `src/components/ui/Button.tsx`

| prop | type | required |
|---|---|:--:|
| `title` | `string` | ✓ |
| `variant` | `'primary' | 'secondary' | 'danger'` | — |

## `Card` — `src/components/ui/Card.tsx`

| prop | type | required |
|---|---|:--:|
| `title` | `string` | — |
| `children` | `React.ReactNode` | — |

## `EmptyState` — `src/components/ui/EmptyState.tsx`

| prop | type | required |
|---|---|:--:|
| `icon` | `IconName` | — |
| `title` | `string` | ✓ |
| `message` | `string` | — |

## `Header` — `src/components/ui/Header.tsx`

| prop | type | required |
|---|---|:--:|
| `title` | `string` | ✓ |
| `onBack` | `() => void` | — |
| `action` | `{ icon: IconName` | — |
| `onPress` | `() => void` | ✓ |
| `label` | `string` | — |

## `Icon` — `src/components/ui/Icon.tsx`

| prop | type | required |
|---|---|:--:|
| `name` | `IconName` | ✓ |
| `size` | `'sm' | 'md' | 'lg' | number` | — |
| `color` | `string` | — |
| `accessibilityLabel` | `string` | — |

## `Input` — `src/components/ui/Input.tsx`

| prop | type | required |
|---|---|:--:|
| `label` | `string` | — |

## `ListItem` — `src/components/ui/ListItem.tsx`

| prop | type | required |
|---|---|:--:|
| `title` | `string` | ✓ |
| `subtitle` | `string` | — |
| `onPress` | `() => void` | — |
| `trailing` | `React.ReactNode` | — |
| `showChevron` | `boolean` | — |

## `Screen` — `src/components/ui/Screen.tsx`

| prop | type | required |
|---|---|:--:|
| `children` | `React.ReactNode` | — |

## `Text` — `src/components/ui/Text.tsx`

_No props — drop-in._
