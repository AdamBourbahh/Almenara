import { BurningCalendarCanvas } from "../components/Calendar/BurningCalendarCanvas";
import { CalendarTooltip } from "../components/Calendar/CalendarTooltip";
import { PageShell } from "./PageShell";

export function CalendarPage() {
  return (
    <PageShell
      eyebrow="The 2012 artefact"
      title="Why the hot-spot count jumped in 2012"
      intro="VIIRS picks up much smaller fires than MODIS. Add the two raw series together and 2012 looks like the year the planet caught fire. The calendar below puts raw counts next to the harmonized energy record so you can see the difference for yourself."
    >
      <div className="relative">
        <BurningCalendarCanvas />
        <CalendarTooltip />
      </div>
    </PageShell>
  );
}
