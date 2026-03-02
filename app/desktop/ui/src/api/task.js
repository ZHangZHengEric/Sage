import { BaseAPI } from "./base"

class TaskAPI extends BaseAPI {
  getRecurringTasks(params) {
    return this.get('/tasks/recurring', params)
  }

  createRecurringTask(data) {
    return this.post('/tasks/recurring', data)
  }

  updateRecurringTask(id, data) {
    return this.put(`/tasks/recurring/${id}`, data)
  }

  deleteRecurringTask(id) {
    return this.delete(`/tasks/recurring/${id}`)
  }

  toggleTaskStatus(id, enabled) {
    return this.post(`/tasks/recurring/${id}/toggle`, { enabled })
  }

  getTaskHistory(id, params) {
    return this.get(`/tasks/recurring/${id}/history`, params)
  }
}

export const taskAPI = new TaskAPI()
