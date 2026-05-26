
---
title: Zapier - Add new Google Drive files to Notion database
deprecated: false
hidden: false
metadata:
  robots: index
---

| Attribute | Value |
| ----------|-------|
| ID | 360080054 |
| Title | Add new Google Drive files to Notion database |
| Status| on |


```mermaid
graph TD
    A["🔍 When new file is added to Google Drive<br/>(Folder: goats_backup)<br/>includeSubfolders: true"]
    B["📝 Format the file name and URL<br/>(Line Itemizer)<br/>Creates: Doc name, Category, URL"]
    C["📌 Add to Notion database<br/>(Document Hub)<br/>Creates entry with formatted data"]
 
    A -->|File: title, webContentLink| B
    B -->|Line items| C

    style A fill:#4285F4,stroke:#333,stroke-width:2px,color:#fff
    style B fill:#FF6D00,stroke:#333,stroke-width:2px,color:#fff
    style C fill:#2D82B7,stroke:#333,stroke-width:2px,color:#fff
```

