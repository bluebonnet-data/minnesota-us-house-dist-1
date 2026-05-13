*![][image1]*

# Bluebonnet Fellowship Partner Project Scoping Doc

# 

# **PROJECT 1: CallTime AI integration with NGP** 

---

## **Project Context, Overview, & Goals:**

The Johnson campaign uses [CallTime.AI](http://calltime.ai).  Their main issue is that there is no API connecting CallTime and NGP, meaning updates must be done manually.  They would like a seamless integration between the two.  They have also noticed that the CallTime lists have many out of date or otherwise “bad” numbers, and they are interested in a way to clean up the call lists. 

## 

## **Key Deliverable(s):**

The primary requests are 1\) an API to upload data from CallTime to NGP and 2\) a way to weed out numbers not connected to likely donors.  The campaign had a few secondary requests: 1\) find a way to automate summaries of calls and 2\) merge data from PhoneBurner (a similar tool they used previously) to CallTime.

## **Existing Work & Stakeholders:**

Tony Eichenlaub has handled most of the data/tech work for the Johnson campaign.  The Johnson campaign recently switched to CallTime from a combination of Phone Burner and Zapier.  The campaign previously used Granola to take notes on calls but stopped a while ago.

## 

## **Timeline:**

There was no formal timeline set, but this was one of their high priority tasks.

## **Data Sources and Tools**

Bluebonnet fellows will need access to the Johnson campaign NGP VAN and [CallTime.AI](http://calltime.ai) data.  Tony and Nik Marda (the campaign manager) will send a data access/NDA form.  
---

## **TECH ADVISING – FOR BLUEBONNET**

## 

### Data Sourcing and Collection

The campaign will provide necessary data.  We will need access to their CallTime and NGP VAN.

### Suggested Methods

Python.  This won’t require many API calls since it’s just internal for the campaign (maybe a few times a day).  They may also be able to run it locally since the datasets exported will be small.

### 

### Skills Required of Fellows

Working with and developing APIs

### Project Summary (for matching)

# **PROJECT 2: Digital Infrastructure for Relational Organizing**

---

## **Project Context, Overview, & Goals:**

The campaign has many volunteers and a strong grassroots presence.  This project is a little less fleshed out, but Nik would like to connect volunteers to people in their social networks for relational organizing.  He envisions volunteers reaching out to persuadable voters or voters who would likely vote for Jake but have a medium probability of turnout.

They are currently using spreadsheets to coordinate volunteers, so a tool to manage that would be helpful, too.

## **Key Deliverable(s):**

1. An automated process to connect campaign volunteers to persuadable voters they know personally.  Nik would prefer that they do not have to download an app to keep it simple and accessible  
   1. This might entail downloading data from social media profiles and matching it to NGP VAN, then constructing lists for volunteers of potential voters they know and can reach out to  
2. A tool to help the campaign manage volunteers

## **Existing Work & Stakeholders:**

Tony is our point person on the data/tech projects.  There is not much existing data/tech work on this project, but the Johnson campaign is active on social media, and volunteers have sent direct messages on TikTok to people who engage with the campaign’s posts.  

In terms of organizing volunteers, Nik has looked into some vendor tools like Rally, but he found it too expensive and not well-suited to the campaign’s needs. They currently have a large spreadsheet for tracking volunteers and relational organizing, but they want something more efficient and scalable.

## 

## **Timeline:**

There were no formal deadlines or milestones discussed.  Nik left this a bit open-ended for Bluebonnet to think creatively about digital relational organizing.

## **Data Sources and Tools**

- Information about volunteers’ social networks (area they live, social media profiles, etc.)  
  - This may raise some privacy concerns, and volunteers might be hesitant to share a lot of info with the campaign  
- NGP VAN access for voter lists  
- Volunteer lists

---

## **TECH ADVISING – FOR BLUEBONNET**

*This is intended for Bluebonnet, but you’re welcome to contribute if you’d like*

## 

### Data Sourcing and Collection

Data will come mainly from the campaign.  We can also explore external providers to match voters to social media profiles and target ads/outreach.

### Suggested Methods

- Other organizing tools like Reach, MiniVAN for relational organizing. The campaign will likely get access to Mobilize from the DCCC     
- Maybe include other data vendors (e.g., L2) to match voters to social media accounts.    
- Data processing to connect volunteers to potential voters.

### Skills Required of Fellows

- Experience with Reach, MiniVAN, Mobilize, etc.   
- Familiarity with L2 or similar data providers    
- Data cleaning and fuzzy matching  
- Experience downloading data from social media accounts.

# **PROJECT 3: Social Media Engagement**

---

## **Project Context, Overview, & Goals:**

Jake Johnson is active on social media, with frequent posts across platforms that often touch on very local issues. Nik would like to leverage social media engagement into volunteer recruitment, but he left the methods up to us.  Nik also wants to connect voter data (voter file and NGP VAN) to social media profiles 

## **Key Deliverable(s):**

The main request is a way for the campaign to track engagement on its social media posts and recruit volunteers/identify potential voters.  Nik and Tony also want to figure out how to engage with young constituents more; engaging them has been a bit of a challenge so far.  They explored geotargeting ads to specific areas where Medicaid cuts forced healthcare facilities to close but have not invested much in this strategy so far.

## **Existing Work & Stakeholders:**

Tony and likely campaign staff in charge of social media posts   

## 

## **Timeline:**

As with the other projects, there are no set timelines, but they would like something up and running soon so they can begin outreach.

## **Data Sources and Tools**

- Data from the campaign’s social media accounts  
- NGP VAN

---

## **TECH ADVISING – FOR BLUEBONNET**

## 

### Data Sourcing and Collection

Campaign NGP VAN data, campaign data on social media posts, possibly external vendor data. 

### Suggested Methods

- ### An API or other process to download data from the various social media accounts and combine them

- ### Data cleaning to match social media profiles with voter data

- ### Data analysis on efficacy of outreach (e.g., does reaching out to people who engage on social media lead to them volunteering with the campaign?)

### Skills Required of Fellows

- Experience downloading data from social media accounts  
- Data cleaning  
- Fuzzy matching

[image1]: <data:image/png;base64,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>