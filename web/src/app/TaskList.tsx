import type { RankedTask, TaskDigest } from "@/lib/events";
import { Badge, Card, TableScroll, fieldsClass, tableClass } from "./Card";
import styles from "./ask.module.css";
import { day } from "./dates";

const URGENCY: Record<RankedTask["urgency"], string> = {
  overdue: "Overdue",
  this_week: "This week",
  soon: "Soon",
  later: "Later",
};

function days(n: number): string {
  return n === 1 ? "1 day" : `${n} days`;
}

/**
 * An officer's top open tasks ranked by urgency × impact: the officer, the date ranked on and the open and overdue
 * counts, then one row per task with its due date (overdue ones marked in words, not colour alone), its score and
 * the reasons for its place.
 */
export function TaskList({ digest, heading = "Top tasks" }: { digest: TaskDigest; heading?: string }) {
  return (
    <Card heading={heading}>
      <dl aria-label="Task summary" className={fieldsClass}>
        <dt>Officer</dt>
        <dd>
          {digest.name} ({digest.title})
        </dd>
        <dt>As of</dt>
        <dd>{day(digest.as_of)}</dd>
        <dt>Open</dt>
        <dd>{digest.open_count}</dd>
        <dt>Overdue</dt>
        <dd>{digest.overdue_count}</dd>
      </dl>
      {digest.tasks.length === 0 ? (
        <p>No open tasks.</p>
      ) : (
        <TableScroll label="Ranked tasks">
          <table className={tableClass}>
            <caption>Ranked tasks</caption>
            <thead>
              <tr>
                <th scope="col">Rank</th>
                <th scope="col">Task</th>
                <th scope="col">Type</th>
                <th scope="col">Due</th>
                <th scope="col">Urgency × impact</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {digest.tasks.map((task) => (
                <tr key={task.task_id} data-overdue={task.overdue}>
                  <td>{task.rank}</td>
                  <th scope="row">
                    <span className={styles.taskId}>{task.task_id}</span> {task.title}
                  </th>
                  <td>{task.task_type}</td>
                  <td>
                    {day(task.due_date)}
                    {task.overdue && (
                      <>
                        {" "}
                        <Badge tone="danger" as="strong">
                          Overdue · {days(task.days_overdue)}
                        </Badge>
                      </>
                    )}
                  </td>
                  <td>
                    {URGENCY[task.urgency]} × {task.impact} impact = {task.score}
                  </td>
                  <td>
                    <ul aria-label={`Why ${task.task_id}`} className={styles.reasons}>
                      {task.reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      )}
    </Card>
  );
}
