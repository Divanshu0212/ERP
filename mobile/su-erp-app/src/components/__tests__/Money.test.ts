/**
 * Guards the format itself rather than the component: a student reading fees
 * needs lakh grouping, and a raw DecimalField string must never reach the
 * screen unformatted.
 */
function format(value: string): string {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? amount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : value;
}

test('groups in lakhs, not thousands', () => {
  expect(format('150000')).toBe('1,50,000.00');
});

test('always shows two decimal places', () => {
  expect(format('1500')).toBe('1,500.00');
});

test('keeps the paise the backend sent', () => {
  expect(format('1234.56')).toBe('1,234.56');
});

test('falls back to the raw string rather than rendering NaN', () => {
  expect(format('not-a-number')).toBe('not-a-number');
});
