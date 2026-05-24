import apiClient from "./client";

export const getCatalog = () =>
  apiClient.get("/agents/catalog").then(r => r.data);

export const getTemplates = () =>
  apiClient.get("/agents/templates").then(r => r.data);
