## 1. Business Requirements

PLG oversees HDB's commercial units, concentrating on leasing properties, managing tenancy agreements, and monitoring the condition of these units. The team ensures that the usage of the commercial unit aligns with operational guidelines while actively maintaining the vibrancy of areas that house HDB commercial shops.

Desired Capabilities:

1. Draft standardized documents such as, but not limited to, emails, contracts, letters, reminder letters and updates to feedback providers.
2. Retrieve and analyse historical records from PLG’s internal databases, including, but not limited to, policies, Standard Operating Procedures (SOPs), and emails.
3. Retrieve and interpret policies and operational guidelines, clearly articulating PLG’s stance on each policy.
4. Retrieve relevant precedent cases to assist users in referencing past experiences and making informed decisions to take appropriate actions.
5. Extract information from structured data using natural-language inquiries.
6. Analyse structured data from databases and Excel files to deliver insights tailored to users' inquiries, incorporating relevant business logic and definitions. Additionally, provide a clear outline of the reasoning steps taken to arrive at the information.
7. The database must be regularly updated to ensure accuracy and relevance for both structured and unstructured data. The System shall interface with sharepoint and lotus note.

Desired Agentic Capabilities:

1. Classify the defects in HDB properties and route the issues to the relevant team via another system (i.e. i-EMS)
2. Notify users of outstanding tasks and prioritize them according to urgency and impact, ensuring that critical tasks are addressed promptly and efficiently to enhance overall productivity.
3. Analyse the database to categorize similar documents, thereby enhancing the information retrieval process and enabling users to request summaries for a specific category.
4. Conduct analysis of the databases to identify any conflicting information, deduplication, outline areas that require further development, and recommend areas for enhancement.
5. Review the documents submitted to HDB to ensure all the necessary documents are submitted, and promptly notify tenants of any missing documents, facilitating smoother transitions and ensuring compliance.

## 2. System Requirements

The proposed System shall function as a "super-librarian", seamlessly interfacing with existing databases, document repositories, and Systems to enable users to quickly locate information through natural language inquiries. It shall retrieve precise, citable answers within defined response times and guide users to relevant resources. Additionally, the System shall conduct data analyses, draft documents using approved templates, and propose tailored solutions based on historical data and policies. It shall interpret documents like a domain expert, delivering context-aware responses. The System shall feature a core chatbot or an AI “front door” that routes inquiries to relevant specialized bots that fuse structured and unstructured data from varied systems, with each specialized bot tailored to address specific types of queries within a multi-agent architecture. Furthermore, the System shall feature agentic capabilities with guardrails to autonomously assess queries and propose context-aware actions, while deferring riskier or/and high-impact actions for human review. It shall learn from user interactions to simplify complex queries and continuously enhance its performance.