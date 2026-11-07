const { Cron } = await import(
  process.env.CRONER_JS ?? new URL("../../croner/src/croner.ts", import.meta.url).href
);
import { readFileSync } from "node:fs";
const cases = JSON.parse(readFileSync(0, "utf8"));
const out = cases.map((c: any) => {
  try {
    const job = new Cron(c.pattern, c.options);
    const r: any = { next: job.nextRuns(c.n, new Date(c.ref)).map(d => d.toISOString()),
      prev: job.previousRuns(c.n, new Date(c.ref)).map(d => d.toISOString()),
      match: job.match(new Date(c.ref)) };
    return r;
  } catch (e) { return { error: true }; }
});
console.log(JSON.stringify(out));
