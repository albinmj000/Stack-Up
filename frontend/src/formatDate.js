const DATE_FORMAT_OPTIONS = {
  day: "2-digit",
  month: "short",
  year: "numeric",
};

function localDate(year, month, day, original) {
  const date = new Date(year, month - 1, day);
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return original;
  }
  return date;
}

export function formatDate(value) {
  if (!value) return "—";

  const text = String(value).trim();
  const yearFirst = text.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/);
  const dayFirst = text.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$/);
  let date;

  if (yearFirst) {
    date = localDate(
      Number(yearFirst[1]),
      Number(yearFirst[2]),
      Number(yearFirst[3]),
      text,
    );
  } else if (dayFirst) {
    const rawYear = dayFirst[3];
    const year = Number(rawYear.length === 2 ? `20${rawYear}` : rawYear);
    date = localDate(year, Number(dayFirst[2]), Number(dayFirst[1]), text);
  } else {
    date = new Date(value);
    if (Number.isNaN(date.getTime())) return text;
  }

  return typeof date === "string"
    ? date
    : date.toLocaleDateString("en-IN", DATE_FORMAT_OPTIONS);
}
