package com.aicare.collector

/**
 * NOT IMPLEMENTED. This is the one piece that needs a real device.
 *
 * Implement against ONE of:
 *   A. Health Connect            — no Samsung approval, smaller data surface
 *   B. Samsung Health Data SDK   — full surface, needs developer mode
 *
 * See android/health-collector/README.md for the Phase 0 checklist that has to
 * be answered before any of this is written.
 *
 * Contract obligations that are easy to get wrong:
 *   - Emit OffsetDateTime strings, never LocalDateTime (the backend rejects
 *     naive timestamps with HTTP 422, deliberately).
 *   - sourceUid must be stable across reads of the same record.
 *   - Leave a field null when the source has no value. Never substitute 0.
 *   - Attribute nothing to a day yourself; the backend does that (sleep is
 *     attributed to the wake-up day, workouts to their start day).
 */

import java.time.LocalDate

interface HealthReader {
    /** Read everything available in [from]..[to] inclusive, local dates. */
    suspend fun read(from: LocalDate, to: LocalDate): IngestPayload
}

class NotImplementedHealthReader : HealthReader {
    override suspend fun read(from: LocalDate, to: LocalDate): IngestPayload =
        throw NotImplementedError(
            "Pick Health Connect or the Samsung Health Data SDK and implement read(). " +
                "Until then, tools/generate_synthetic.py feeds the backend."
        )
}
