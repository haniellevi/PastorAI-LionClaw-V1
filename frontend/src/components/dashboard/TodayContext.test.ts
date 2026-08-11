import { describe, expect, it } from "vitest";

import type { EventItem } from "@/lib/events-api";

import { selectUpcomingEvents } from "./TodayContext";

function event(id: string, data: string | null, hora: string | null): EventItem {
  return {
    id,
    titulo: id,
    data,
    hora,
    descricao: null,
    googleEventId: null,
    sincronizado: false,
  };
}

describe("selectUpcomingEvents", () => {
  it("remove passado e recorrência sem data, ordena e limita", () => {
    const now = new Date(2026, 7, 11, 9, 0, 0);
    const result = selectUpcomingEvents(
      [
        event("depois", "2026-08-13", "20:00"),
        event("recorrente", null, "19:00"),
        { ...event("pendente", "2026-08-11", "07:00"), status: "a_confirmar" },
        event("cedo", "2026-08-11", "08:00"),
        event("passado", "2026-08-10", "20:00"),
        event("tarde", "2026-08-11", "19:30"),
        event("quarto", "2026-08-14", "18:00"),
      ],
      now,
      3,
    );

    // `a_confirmar` já chega exclusivamente para pastor/admin, filtrado no
    // servidor; quando presente, o painel deve mostrá-lo como ação pendente.
    expect(result.map((item) => item.id)).toEqual(["pendente", "cedo", "tarde"]);
  });
});
