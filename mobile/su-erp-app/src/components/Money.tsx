import { Text, type TextProps } from 'react-native';

/**
 * Renders a DRF DecimalField string. Never does arithmetic on it beyond the
 * single Number() needed to format.
 *
 * Grouping is en-IN, so 150000 reads as ₹1,50,000 — the lakh grouping every
 * student here reads fees in, not the thousands grouping.
 */
export function Money({ value, ...props }: { value: string } & TextProps) {
  const amount = Number(value);

  const display = Number.isFinite(amount)
    ? amount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value;

  return <Text {...props}>₹{display}</Text>;
}
