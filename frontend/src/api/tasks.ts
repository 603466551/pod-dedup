import axios from "axios";

export type TaskType = "SOURCE_DEDUP" | "SOURCE_ORGANIZE" | "POD_DEDUP" | "POD_CROP" | "INDEX_REBUILD";
export type Task = {
  task_id: string;
  type: TaskType;
  status: string;
  warnings: string[];
  counters: Record<string, number>;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
};

export async function createTask(path: string, payload: Record<string, unknown>): Promise<Task> {
  const { data } = await axios.post(`/api/v1/tasks/${path}`, payload);
  return data;
}

export async function listTasks(): Promise<Task[]> {
  const { data } = await axios.get("/api/v1/tasks");
  return data.items;
}
