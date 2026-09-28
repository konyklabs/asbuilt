export interface JobSchedule {
  name: string;
  cron: string;
}

export interface Schedules {
  timezone: string;
  jobs: JobSchedule[];
}

/**
 * Cron expressions and a shared timezone read together at process start;
 * nothing in this module parses or schedules them, that's left to the
 * caller.
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
 * A no-op when the lock is already held, rather than queuing or throwing;
 * a caller that needs to know whether `fn` actually ran should check
 * separately.
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
