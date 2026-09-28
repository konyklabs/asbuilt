export interface JobSchedule {
  name: string;
  cron: string;
}

export interface Schedules {
  timezone: string;
  jobs: JobSchedule[];
}

/**
 * The dispatch job schedules, evaluated in America/New_York: nightly-rebalance
 * runs every day at 03:00; maintenance-sweep runs every hour on the hour;
 * weather-poll runs every 15 minutes.
 */
export const SCHEDULES: Schedules = {
  timezone: "America/New_York",
  jobs: [
    { name: "nightly-rebalance", cron: "0 3 * * *" },
    { name: "maintenance-sweep", cron: "0 * * * *" },
    { name: "weather-poll", cron: "*/15 * * * *" },
  ],
};

export interface JobLock {
  tryAcquire(name: string): boolean;
  release(name: string): void;
}

/** An in-memory lock held by at most one caller per job name at a time. */
export class InMemoryJobLock implements JobLock {
  private readonly held = new Set<string>();

  tryAcquire(name: string): boolean {
    if (this.held.has(name)) {
      return false;
    }
    this.held.add(name);
    return true;
  }

  release(name: string): void {
    this.held.delete(name);
  }
}

/**
 * Runs `fn` while holding a database lock named after `jobName`, so only
 * one instance of that job runs at a time; a second caller finding the
 * lock held does nothing.
 */
export async function withJobLock(lock: JobLock, jobName: string, fn: () => Promise<void>): Promise<void> {
  if (!lock.tryAcquire(jobName)) {
    return;
  }
  try {
    await fn();
  } finally {
    lock.release(jobName);
  }
}
